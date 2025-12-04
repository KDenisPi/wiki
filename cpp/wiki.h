/**
 * @file wiki.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-09-12
 *
 * @copyright Copyright (c) 2025
 *
 */
#ifndef WIKI_WIKI
#define WIKI_WIKI

#include <atomic>
#include <condition_variable>
#include <thread>
#include <mutex>
#include <pthread.h>
#include <sched.h>
#include <algorithm>

#include "defines.h"
#include "gconfig.h"
#include "item_reader.h"
#include "item_parser.h"
#include "prop_dict.h"
#include "receiver_impl.h"

namespace wiki {

class WiKi : public GConfig {
public:
    /**
     * @brief Construct a new WiKi object
     *
     */
    WiKi() {
        props = std::make_shared<Properties>();
        receiver = std::make_shared<ReceiverImpl>();

        for(int i = 0; i < max_threads; i++){
            buffers[i] = std::shared_ptr<char>(new char[max_buffer_size]);
            threads_vars[i] = 0;
        }

        load_important_properties();
    }

    /**
     * @brief Destroy the WiKi object
     *
     */
    virtual ~WiKi() {

        if(position_info_stream.is_open()){
            position_info_stream.close();
        }
    }

    /**
     * @brief Max number of parser threads
     *
     */
    const static unsigned int max_threads = MAX_PARSING_THREADS; //5;

    /**
     * @brief Maximum size of Wiki Item
     *
     */
    const static size_t max_buffer_size = MAX_LINE_LENGTH;

    /**
     * @brief Parser thread synchronization
     *
     */
    std::atomic_int threads_vars[max_threads];

    /**
     * @brief Read buffers
     *
     */
    std::shared_ptr<char> buffers[max_threads];

    /**
     * @brief Threads pool
     *
     */
    std::thread threads[max_threads];

    /**
     * @brief
     *
     */
    void worker();


    /**
     * @brief
     *
     * @return * void
     */
    void start(){

        receiver->load();

        auto hw_concurrency = std::thread::hardware_concurrency();
        std::cout << "HW Concurrency : " << hw_concurrency << std::endl;
        const auto assign_threads = (use_concurrency && (hw_concurrency > max_threads));

        for(int i = 0; i < max_threads; i++){
            parsers[i] = std::make_shared<ItemParser>(i, &threads_vars[i], buffers[i], props, receiver);
            threads[i] = std::thread(&ItemParser::worker, parsers[i].get());
            if(assign_threads){
                setThreadAffinity(threads[i], i);
            }
        }

        th_main = std::thread(&WiKi::worker, this);
        if(assign_threads){
            setThreadAffinity(th_main, max_threads);
        }
        th_main.join();

        receiver->save();
    }

    /**
     * @brief Set the Thread Affinity object
     *
     * @param th
     * @param core_id
     * @return true
     * @return false
     */
    bool setThreadAffinity(std::thread& th, int core_id){
        cpu_set_t cpuset;
        CPU_ZERO(&cpuset);           // Clear the CPU set
        CPU_SET(core_id, &cpuset);   // Add the desired core to the set

        // Get the native pthread handle from the std::thread object
        pthread_t handle = th.native_handle();

        // Set the CPU affinity
        int result = pthread_setaffinity_np(handle, sizeof(cpu_set_t), &cpuset);
        if (result != 0) {
            std::cerr << "Error setting thread affinity: " << result << std::endl;
            return false;
        }

        std::cout << "Thread affinity " << handle << " set to core " << core_id << std::endl;
        return true;
    }


    /**
     * @brief
     *
     * @return true
     * @return false
     */
    const bool is_finish() const{
        return finish;
    }

    /**
     * @brief Set the finish object
     *
     */
    void set_finish(){
        //const std::lock_guard<std::mutex> lock(cv_m);
        finish = true;
    }

    /**
     * @brief Initialize reader object
     *
     * @param filename
     * @return true
     * @return false
     */
    bool load_source(const std::string& filename){
        return reader.init(filename);
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    bool load_properties(const std::string& filename){
        const bool res =  props->load(filename);
        return res;
    }

    /**
     * @brief
     *
     */
    void load_important_properties(){
        /*
        P569; date of birth; date on which the subject was born
        P570; date of death; date on which the subject died
        P571; inception; time when an entity begins to exist;  for date of official opening use P1619
        P575; time of discovery or invention; date or point in time when the item was discovered or invented
        P577; publication date; date or point in time when a work was first published or released
        P580; start time; time an entity begins to exist or a statement starts being valid
        P582; end time; moment when an entity ceases to exist and a statement stops being entirely valid or no longer be true
        P585; point in time; date something took place, existed or a statement was true;  for providing time use the "refine date" property (P4241)
        P1619; date of official opening; date or point in time a place, organization, or event officially opened
        P3999; date of official closure; date of official closure of a building or event
        P6949; announcement date; time of the first public presentation of a subject by the creator, of information by the media
        P7124; date of the first one; qualifier: when the first element of a quantity appeared/took place
        P7125; date of the latest one; qualifier: when the latest element of a quantity appeared/took place
        P10135; recording date; the date when a recording was made
        P10673; debut date; date when a person or group is considered to have "debuted"
        */

        std::vector<std::string> v_props = {"P569","P570", "P571", "P575", "P577", "P580", "P582", "P585", "P1619",\
            "P3999", "P6949", "P7124", "P7125", "P10135", "P10673"};

        props->load_important_property(v_props);

        //P31;instance of;
        //type to which this subject corresponds/belongs. Different from P279 (subclass of);
        //for example: K2 is an instance of mountain; volcanoes form a subclass of mountains,
        //and the volcano is a type (instance) of volcanic landform

        /*
        Q5; human; any single member of Homo sapiens, unique extant species of the genus Homo

        Q13418847; historical event; particular incident in history that brings about a historical change
        Q1656682; event; temporary and scheduled happening, like a conference, festival, competition or similar
        Q58687420; cultural event; event of cultural kind
        Q24336466; mythical event; event that only appears in myths and legends
        Q30111082; political event; temporary and scheduled happening with political nature, origin, or consequences
        Q2680861; transient astronomical event; briefly-observed celestial event
        Q55814; extinction event; widespread and rapid decrease in the amount of life on earth
        Q2245405; key event; class of items used with property 'significant event' (P793)
        Q113162275; music event; event where music is performed
        Q52260246; scientific event; type of event;  occurrence of scientific interest, import, or purpose
        Q110799181; in-person event; event held in person
        Q106518893; entity in event;
        Q463796; impact event; collision of two astronomical objects with measurable effects
        Q1568205; literary event;
        Q2136042; arts event;
        Q117769381; social event; occasion where people assemble a series of events
        Q109975697; geological event; type of event
        Q108586636; form of event; metaclass, grouping forms and types of events by specificity

        Q105543609; musical work/composition; Wikidata metaclass;  legal concept of uniquely identifiable piece or work of music, either vocal or instrumental;  NOT applicable to recordings, broadcasts, or individual publications of music in printed or digital form or on physical media
        Q107487333; type of musical work/composition; Wikidata metaclass
        Q2188189; musical work; generic term for any work of art related to music, i.e. songs, compositions, groups of compositions, sheet music, melodies, albums, musical films, etc.
        Q207628; composed musical work; original piece or work of music, either vocal or instrumental
        Q22965078; Wikidata property for items about musical works; type of Wikidata property
        Q28146956; Wikidata property to identify musical works; Wikidata property what identify musical works


        Q12737077; occupation; label applied to a person based on an activity they participate in
        Q135106813; musical occupation; main vocalist
        Q15839299; theatrical occupation; occupation related to the performing arts
        Q63187345; religious occupation; occupation or profession that serves a purpose within the context of a religion
        Q66666236; Wikimedia list of persons by occupation; page on a Wikimedia project listing persons by their occupation

        ----
        Q6256; country; distinct territorial body or political entity
        Q5107; continent; large landmass identified by convention

        --- updates -------
        [add 24.11.2025]Q93288;contract;agreement having a lawful object entered into voluntarily by multiple parties (may be explicitly written or oral)
        [Add,24.11.2025]Q11514315;historical period;segment of time in history
        [Add,24.11.2025]Q103495;world war;large-scaled international military conflict
        */

        std::vector<pID> v_instance_of_values = {
            "Q5", "Q13418847", "Q1656682", "Q58687420", "Q24336466", "Q30111082", "Q2680861", "Q55814", "Q2245405",
            "Q113162275", "Q52260246", "Q110799181", "Q106518893", "Q463796", "Q1568205", "Q2136042", "Q117769381",
            "Q109975697", "Q108586636", "Q105543609", "Q107487333", "Q2188189", "Q207628", "Q22965078", "Q28146956",
            "Q12737077", "Q135106813", "Q15839299", "Q63187345", "Q66666236", "Q6256", "Q5107", "Q93288", "Q11514315", "Q103495"
        };

        props->load_instance_of_property(v_instance_of_values);
    }


    /**
     * @brief
     *
     * @param filename
     */
    void load_position_file(const std::string& filename){
        if(filename.empty())
            return;

        position_file = filename;

        if(!position_file.empty()){
            //Open position info file for appending and move position to the end
            position_info_file = filename + ".info";
            std::cout << "Position info file: " << position_info_file << std::endl;

            position_info_stream.open(position_info_file, std::ios::out | std::ios::app);
            if(position_info_stream.is_open()){
                position_info_stream.seekg(0, std::fstream::end);
            }
            else{
                std::cerr << "Could not open position info file for appending: " << position_info_file << std::endl;
            }
        }

        std::ifstream inputFile(filename);
        if(inputFile.is_open()){
            std::string line;
            while(std::getline(inputFile, line)){
                long pos = std::stol(line);
                if(pos > 0){
                    std::cout << "Start from position : " << pos << std::endl;
                    reader.set_pos(pos);
                }
            }

            inputFile.close();
        }
    }

    /**
     * @brief Set the flush bulk object
     *
     * @param fl_size
     */
    void set_flush_bulk(const long fl_size){
        flush_bulk = fl_size;
    }

    /**
     * @brief Get the flush bulk object
     *
     * @return const long
     */
    inline const long get_flush_bulk() const{
        return flush_bulk;
    }

    /**
     * @brief Get the bulk size object
     *
     * @return const unsigned long
     */
    inline const unsigned long get_bulk_size() const {
        return bulk_size;
    }

    /**
     * @brief Set the bulk size object
     *
     * @param bl_size
     */
    void set_bulk_size(const unsigned long bl_size){
        bulk_size = bl_size;
    }

    /**
     * @brief Get the save pos every object
     *
     * @return const long
     */
    inline const long get_save_pos_every() const {
        return save_pos_every;
    }

    /**
     * @brief Set the save position every object
     *
     * @param sp_every
     */
    void set_save_pos_every(const long sp_every){
        save_pos_every = sp_every;
    }

private:
    std::mutex cv_m;
    std::thread th_main;

    bool finish = false;
    bool use_concurrency = true;    //Try to assign working thread to the separate cores if it is possible

    std::shared_ptr<ItemParser> parsers[max_threads];
    std::shared_ptr<Properties> props;

    std::shared_ptr<Receiver> receiver;

    ItemReader reader;
    std::string position_file;
    std::string position_info_file;

    long flush_bulk = 10000;
    unsigned long bulk_size = 0;

    long save_pos_every = 100000;  //Save position in file for every N items processed (100K*Threads)
    std::fstream position_info_stream;

    /**
     * @brief Save the current position to the position file
     *
     */
    void save_position_file(){
        std::fstream outputFile(position_file, std::ios::out);
        if(outputFile.is_open()){
            auto pos = reader.get_pos();
            outputFile << std::to_string(pos) << std::endl;
            outputFile.close();
        }
    }

    /**
     * @brief Append the current position info to the position info file
     *
     * @param item_index
     */
    void save_position_info(const long item_index){
        if(position_info_stream.is_open()){
            auto pos = reader.get_pos();
            position_info_stream << std::to_string(item_index) << "," << std::to_string(pos) << std::endl;
        }
    }

};

}//namespace

#endif
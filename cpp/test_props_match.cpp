/**
 * @file test_props_match.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-08
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <string>
#include <memory>

#include "rapidjson/document.h"
#include "smallthings.h"

#include "prop_dict.h"
#include "item_reader.h"
#include "item_parser.h"
#include "receiver_easy.h"
#include "receiver_impl.h"

int main (int argc, char* argv[])
{
    int status = EXIT_SUCCESS;
    if(argc < 3){
        std::cout << "Absent necassary data files." << std::endl << "Using: test_props prop_dict.json item.json" << std::endl;
        exit(EXIT_FAILURE);
    }

    std::shared_ptr<char> buffer = std::shared_ptr<char>(new char[MAX_LINE_LENGTH]);// Declare a character array (buffer) to store the line

    std::shared_ptr<wiki::Properties> ptr_props = std::make_shared<wiki::Properties>();
    if(!ptr_props->load(std::string(argv[1]))){
        exit(EXIT_FAILURE);
    }

    std::cout << argv[1] << " Props count: " << ptr_props->MemberCount() << std::endl;
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

    std::vector<wiki::pID> v_props = {"P569","P570", "P571", "P575", "P577", "P580", "P582", "P585", "P1619",\
        "P3999", "P6949", "P7124", "P7125", "P10135", "P10673"};
    ptr_props->load_important_property(v_props);

    std::vector<wiki::pID> v_instance_of_values = {
        "Q5", "Q13418847", "Q1656682", "Q58687420", "Q24336466", "Q30111082", "Q2680861", "Q55814", "Q2245405",
        "Q113162275", "Q52260246", "Q110799181", "Q106518893", "Q463796", "Q1568205", "Q2136042", "Q117769381",
        "Q109975697", "Q108586636", "Q105543609", "Q107487333", "Q2188189", "Q207628", "Q22965078", "Q28146956",
        "Q12737077", "Q135106813", "Q15839299", "Q63187345", "Q66666236", "Q6256", "Q5107", "Q93288", "Q11514315", "Q103495"
    };

    ptr_props->load_instance_of_property(v_instance_of_values);


    //auto p_found = ptr_props->is_important_property("P571");
    //std::cout << " P571 Found: " << p_found << std::endl;

    std::unique_ptr<wiki::ItemReader> ptr_reader = std::make_unique<wiki::ItemReader>();
    if(ptr_reader->init(std::string(argv[2]))){
        std::atomic_int sync;
        std::shared_ptr<char> fake_buff;
        std::shared_ptr<wiki::Receiver> receiver = std::make_shared<wiki::ReceiverImpl>();

        auto r_res = ptr_reader->next(buffer.get(), MAX_LINE_LENGTH);
        while(r_res != wiki::ItemReader::END_OF_FILE){
            if(wiki::ItemReader::Res::OK == r_res){
                std::unique_ptr<wiki::ItemParser> ptr_item = std::make_unique<wiki::ItemParser>(0, &sync, fake_buff, ptr_props, receiver);
                std::vector<std::string> lng = {"ru"};

                if(ptr_item->load(buffer.get())){
                    auto ptr_item_doc = ptr_item->get();

                    int interesting_item = 0;
                    const auto itm = ptr_item->parse_item(lng);

                    const auto item_id = std::get<0>(itm);
                    if(!item_id.empty()){
                        std::cout << "Item ID: " << item_id;
                        for(auto val : std::get<1>(itm)){
                            std::cout << ";" << val;
                        }
                        std::cout << std::endl;
                    }

                    auto v_claims = ptr_item_doc->FindMember("claims");
                    if(v_claims != ptr_item_doc->MemberEnd()){
                        //Detect "Instance of" property for this Item
                        auto p31 = v_claims->value.FindMember(ptr_item->s_P31.c_str());
                        if( v_claims->value.MemberEnd() != p31){
                            wiki::prop_ids pids;
                            auto insts = ptr_item->get_instance_of(p31, pids);
                            for(auto p31_inst : pids){
                                if(ptr_props->is_useful_instance_of_value(p31_inst)){

                                    receiver->put_dictionary_value("ItemsExt", item_id, std::get<1>(itm));

                                    auto ptr_props_doc = ptr_props->get();
                                    for(auto cl_v = v_claims->value.MemberBegin(); cl_v != v_claims->value.MemberEnd(); ++cl_v){
                                        ptr_item->parse_claim(cl_v, item_id, p31_inst);
                                    }
                                    break;
                                }
                            }

                            // Debug output
                            if( false ){
                                std::cout << "P31 Instance of:";
                                for(auto p31_inst : pids){
                                    std::cout << " " << p31_inst;
                                    if(ptr_props->is_useful_instance_of_value(p31_inst)){
                                        std::cout << "[Y]";
                                        interesting_item++;
                                    }
                                }
                                if( interesting_item==0 ){
                                    std::cout << " --- Not interesting. Ignore";
                                }
                                if( interesting_item>1 ){
                                    std::cout << " --- More than one P31";
                                }
                                std::cout << std::endl;
                            }
                        }
                    }
                    else
                        std::cout << "No such member: " << "claims" << std::endl;
                }
                else{
                    std::cout << "No such parse buffer: " << std::endl;
                }
            }
            r_res = ptr_reader->next(buffer.get(), MAX_LINE_LENGTH);
        }

        receiver->save();
    }
    else{
        std::cout << "Could not init reader for: " << std::string(argv[2]) << std::endl;
    }

    exit(status);
}
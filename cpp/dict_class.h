/**
 * @file dict_class.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief Serbice class for dictionary objects (for example instance types etc)
 * @version 0.1
 * @date 2025-09-24
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_DICT_CLASS_H_
#define WIKI_DICT_CLASS_H_

#include <map>
#include <tuple>
#include <string>
#include <cassert>
#include <mutex>
#include <atomic>
#include <fstream>
#include <utility>

namespace wiki{

template<typename K, typename V>
class DictClass{
public:
    DictClass(const std::string& name) : dict_name(name) {
        dict_filename = name + ".csv";
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    virtual const int load(const std::string& filename = ""){
        int count = 0;
        const auto f_name = (filename.empty() ? dict_filename : filename);

        {
            const std::lock_guard<std::mutex> lock(mtx);
            std::ifstream inputFile((filename.empty() ? dict_filename : filename));
            if(inputFile.is_open()){
                std::string line;
                while(std::getline(inputFile, line)){
                    const auto off = line.find(";");
                    const std::string item_id = line.substr(0, off);
                    p_dict_exists[item_id] = "";
                    count++;
                }

                inputFile.close();
            }
        }

        std::cout << "Dictionary " << dict_name << " loaded from: " << f_name << " Size: " << p_dict_exists.size() << std::endl;
        return count;
    }

    template <typename Tuple, typename F, std::size_t... I>
    void for_each_impl(Tuple&& t, F&& f, std::index_sequence<I...>) {
        (f(std::get<I>(std::forward<Tuple>(t))), ...); // Fold expression (C++17)
    }

    template <typename Tuple, typename F>
    void for_each(Tuple&& t, F&& f) {
        for_each_impl(std::forward<Tuple>(t), std::forward<F>(f),
                    std::make_index_sequence<std::tuple_size_v<std::decay_t<Tuple>>>{});
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    virtual const bool save(const bool flush = false, const std::string& filename = ""){
        bool result = true;
        const auto f_name = (filename.empty() ? dict_filename : filename);

        std::cout << "Dictionary " << dict_name << " save to: " << f_name << " Flush(" << flush << ") Size to save: " << p_dict.size();
        if(!flush){
            std::cout << std::endl;
        }

        const std::lock_guard<std::mutex> lock(mtx);
        std::fstream outputFile(f_name, std::ios::out | std::ios::app);
        if(outputFile.is_open()){
            outputFile.seekg(0, std::fstream::end);
            for( auto it = p_dict.begin(); it != p_dict.end(); ++it ){
                if(flush){
                    p_dict_exists[it->first] = "";
                }

                outputFile << it->first;
                for_each(it->second, [&](const auto& val) {
                    outputFile << ";" << val;
                });
                outputFile << std::endl;
            }
            outputFile.close();

            //clean disctionalty after saving
            if(flush){
                p_dict.clear();
                std::cout << " Full size: " << p_dict_exists.size() << std::endl;
            }
        }
        else{
            result = false;
        }

        return result;
    }


    /**
     * @brief
     *
     * @param key
     * @param val
     */
    void put(const K& key, const V& val){
        assert((std::string(typeid(val).name()).find("tuple") != std::string::npos));

        const std::lock_guard<std::mutex> lock(mtx);

        //check if we have already had this key before
        if( p_dict_exists.size() > 0 && p_dict_exists.end() != p_dict_exists.find(key)){
            return;
        }

        p_dict[key] = val;
    }


    /**
     * @brief Get the load at start object
     *
     * @return true
     * @return false
     */
    inline bool get_load_at_start() const {
        return load_at_start;
    }


    /**
     * @brief Set the load at start object
     *
     * @param load_values
     */
    inline void set_load_at_start(const bool load_values){
        load_at_start = load_values;
    }

private:
    std::mutex mtx;
    std::map<K,V> p_dict;
    std::map<K,K> p_dict_exists;

    std::string dict_name;
    std::string dict_filename;

    bool load_at_start = true; //we will load values from the storage at start by default but will change it sometimes
};

}//namespace wiki

#endif
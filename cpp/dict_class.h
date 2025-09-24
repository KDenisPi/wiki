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

namespace wiki{

template<typename K, typename V>
class DictClass{
public:
    DictClass(){

    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    virtual const bool load(const std::string& filename){

        return true;
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    virtual const bool save(const std::string& filename){
        return true;
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

    }

private:
    std::mutex mtx;
    std::map<K,V> p_dict;
};

}//namespace wiki

#endif